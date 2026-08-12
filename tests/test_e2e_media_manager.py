"""Playwright e2e for the media manager's replace action.

Separate from test_e2e_media_picker.py, which drives the in-editor picker, has
no MEDIA_ROOT isolation, and seeds byte-less assets. Both of those would make
the central assertion here -- that the rendered src actually changes -- pass on
a build that replaced nothing.
"""

import os
from io import BytesIO

import pytest
from PIL import Image
from playwright.sync_api import expect

from courses.models import ImageElement
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

# Every test below also carries @pytest.mark.django_db(transaction=True),
# matching tests/test_e2e_media_picker.py:83 and tests/test_e2e_before_after.py
# :838. pytest-django's _live_server_helper pulls `transactional_db` in anyway,
# so it changes nothing at runtime -- it is written out so the DB contract is
# visible to a reader rather than implied by a fixture two layers down.


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists.

    autouse deliberately: a fixture defined in a test module is scoped to that
    module and cannot leak, whereas an opt-in redirect that a future test forgets
    would write into -- and, uniquely for THIS feature, DELETE from -- the
    working tree's real media/ directory.

    It is also what makes the served bytes the test's bytes: live_server DOES
    serve /media/ from MEDIA_ROOT, resolved per request (see the module
    docstring of tests/test_e2e_imagezoom.py), which is why the redirect must
    happen BEFORE any asset is created rather than merely before the first page
    load -- otherwise a fixture image's bytes and the path being served diverge.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _png_bytes(size=(4, 4), color="blue"):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _upload_payload(name="replacement.png", color="green"):
    return {"name": name, "mimeType": "image/png", "buffer": _png_bytes(color=color)}


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(username, slug, *, with_element=True):
    """A course whose asset has REAL bytes and a storage-assigned name, so the
    replacement genuinely lands on a different URL."""
    owner = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    asset = make_image_asset(course, filename="original.png", color="red")
    if with_element:
        add_element(unit, ImageElement.objects.create(media=asset, alt="a"))
    return owner, course, unit, asset


def _open_manager(page, live_server, username, course):
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/media/")
    page.wait_for_selector(".asset-cell")


def _seed_assets(username, slug, *specs):
    """Course + exactly the named assets, nothing else.

    Distinct from _seed(): that one creates an `original.png` of its own, which
    would add an unrelated cell to every grid the preview rows measure.

    NOTE the grid order: courses/media.py:86 sorts by "-created", so the LAST
    spec here renders FIRST. Resolve anchors by name, not by nth().
    """
    user = make_verified_user(username)
    course = CourseFactory(owner=user, slug=slug)
    for filename, size in specs:
        make_image_asset(course, filename=filename, size=size)
    return user, course


def _anchor(page, filename):
    """The [data-asset-preview] of the cell whose data-name is `filename`.

    data-name lives on the .asset-cell ROOT (_asset_cell.html:3), not on a
    descendant -- so this is an attribute selector on the cell itself. Do not
    "fix" it to `.asset-cell:has([data-name=...])`: :has() takes a relative
    selector defaulting to the descendant combinator and would match nothing.
    """
    return page.locator(f'.asset-cell[data-name="{filename}"] [data-asset-preview]')


def _open_preview(page, filename):
    """Hover the named thumb and wait past the dwell. Every overlay test uses it.

    By NAME, never by nth(): the grid sorts "-created" (courses/media.py:86), so
    the last asset seeded renders first.
    """
    _anchor(page, filename).hover()
    expect(page.locator(".asset-preview")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_replace_swaps_the_cell_and_the_rendered_image(page, live_server):
    _, course, unit, asset = _seed("pa-repl-e2e", "repl-e2e")
    _open_manager(page, live_server, "pa-repl-e2e", course)
    original_src = asset.file.url

    # The input is shared across the whole manager now -- hoisted onto
    # .media-manager, outside .asset-grid, so a cell/grid swap can never
    # detach it while the OS dialog is open. It therefore only knows which
    # asset it is picking for via the pk the ⇄ click handler records. Every
    # test below drives the real click-then-choose path rather than setting
    # the input's files directly: a direct set_input_files with no click
    # first would leave the pending pk unset and the change handler would
    # find no cell to attach a strip to.
    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(_upload_payload())

    strip = page.locator("[data-replace-strip]")
    strip.wait_for(state="visible")
    assert "replacement.png" in strip.locator("[data-replace-filename]").inner_text()
    # The confirm must not destroy the context the author decides against.
    assert page.locator(".asset-uses").is_visible()
    # Focus moves to the strip's commit action as soon as it appears: the file
    # input is hidden and never takes focus, so without this the author is left
    # silently on ⇄ with no cue new content arrived.
    assert page.evaluate("document.activeElement.hasAttribute('data-replace-commit')")

    strip.locator("[data-replace-commit]").click()

    # Wait on the STRIP going away, then assert the filename inside
    # `.asset-dname` -- the server-rendered node. A bare
    # `.asset-cell:has-text("replacement.png")` would be satisfied the instant
    # the strip appears, because :has-text matches DESCENDANTS and
    # [data-replace-filename] holds exactly that name. The wait would then be a
    # no-op and everything after it would race the round-trip. `.asset-dname`
    # preserves that property -- [data-replace-filename] is not a descendant of
    # it -- so do NOT "simplify" this back to `.asset-cell`.
    page.wait_for_selector("[data-replace-strip]", state="detached")
    page.wait_for_selector('.asset-cell .asset-dname:has-text("replacement.png")')
    # focusTrigger(fresh) moves focus to the fresh cell's own ⇄, not merely
    # somewhere on the page.
    assert page.evaluate("document.activeElement.hasAttribute('data-replace-asset')")

    editor_url = (
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.goto(editor_url)
    page.wait_for_selector('[data-scope="editor"]')
    new_src = page.locator(".prev-el img").first.get_attribute("src")
    assert new_src != original_src  # it moved...
    assert "replacement" in new_src  # ...and to the file we uploaded


@pytest.mark.django_db(transaction=True)
def test_cancel_changes_nothing_and_sends_no_request(page, live_server):
    _, course, _unit, asset = _seed("pa-repl-cancel", "repl-cancel")
    _open_manager(page, live_server, "pa-repl-cancel", course)

    # Recorded BEFORE the click, so the negative is asserted rather than slept on.
    seen = []
    page.on("request", lambda r: seen.append(r.url) if "/replace/" in r.url else None)

    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(_upload_payload())
    strip = page.locator("[data-replace-strip]")
    strip.wait_for(state="visible")
    strip.locator("[data-replace-cancel]").click()
    # The strip's removal provably post-dates any request the handler would make.
    page.wait_for_selector("[data-replace-strip]", state="detached")
    # focusTrigger() (no arg -> cell) puts focus back on ⇄, not dropped to <body>.
    assert page.evaluate("document.activeElement.hasAttribute('data-replace-asset')")

    assert seen == []
    # The input must be CLEARED, not merely abandoned: `change` fires only on a
    # value change, so leaving the old value would make re-picking the SAME file
    # a dead click. Nothing else in this module reads input.value, so without
    # this assertion `closeStrip`'s clearInput argument is untested everywhere.
    assert page.input_value("[data-replace-input]") == ""
    asset.refresh_from_db()
    assert asset.original_filename == "original.png"


@pytest.mark.django_db(transaction=True)
def test_a_422_flashes_the_validator_message(page, live_server):
    _, course, _unit, _asset = _seed("pa-repl-422", "repl-422")
    _open_manager(page, live_server, "pa-repl-422", course)

    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(
        {"name": "clip.mp4", "mimeType": "video/mp4", "buffer": b"\x00" * 256}
    )
    page.locator("[data-replace-commit]").click()

    bar = page.locator(".op-error")
    bar.wait_for(state="visible")
    text = bar.inner_text()
    # CONTAINMENT, not equality: _op_error.html renders
    # "Couldn't apply that change: {{ message }}", so the extracted textContent
    # always carries that prefix. An equality assertion would be red against a
    # correct build. Nobody should "fix" that by stripping the prefix in JS.
    assert "mp4" in text.lower()
    assert "<" not in text  # the fragment was parsed, not dumped
    assert bar.get_attribute("role") == "alert"  # announced, not silent
    assert page.locator("[data-replace-strip]").count() == 0
    assert page.input_value("[data-replace-input]") == ""


@pytest.mark.django_db(transaction=True)
def test_a_server_error_removes_the_strip_and_flashes(page, live_server):
    """Every other e2e here passes with the catch-all branch deleted."""
    _, course, _unit, _asset = _seed("pa-repl-500", "repl-500")
    _open_manager(page, live_server, "pa-repl-500", course)
    page.route("**/replace/", lambda route: route.fulfill(status=500, body="boom"))

    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(_upload_payload())
    page.locator("[data-replace-commit]").click()

    page.wait_for_selector("[data-replace-strip]", state="detached")
    assert page.locator(".op-error").is_visible()
    assert page.input_value("[data-replace-input]") == ""
    focused = page.evaluate("document.activeElement.hasAttribute('data-replace-asset')")
    assert focused  # focus restored, not dropped to <body>


@pytest.mark.django_db(transaction=True)
def test_two_consecutive_replaces_both_succeed(page, live_server):
    """Carries two regressions at once.

    The per-strip `done` closure: hoisted, the second replace is a silent no-op.
    The in-flight flag's LOWERING: it is read in exactly one place, the ⇄ click
    handler -- so the second pass must go through an actual CLICK (both passes
    do, now that the shared input requires it -- but the second is what proves
    the flag was actually lowered: a flag raised and never lowered would make
    THIS click return early, no chooser would be raised, and the test would
    hang rather than fail cleanly).
    """
    _, course, _unit, _asset = _seed("pa-repl-twice", "repl-twice")
    _open_manager(page, live_server, "pa-repl-twice", course)

    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(_upload_payload("first.png"))
    page.locator("[data-replace-commit]").click()
    # Detached-first, then .asset-dname -- see the note in the happy-path test.
    # Getting this wrong is not cosmetic here: a no-op wait would run the click
    # below while replaceBusy is still true, the handler would return early, no
    # chooser would be raised, and the test would time out ON A CORRECT BUILD.
    page.wait_for_selector("[data-replace-strip]", state="detached")
    page.wait_for_selector('.asset-cell .asset-dname:has-text("first.png")')

    # Second pass THROUGH the button. input.click() raises a file chooser that
    # must be intercepted, or it hangs.
    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(_upload_payload("second.png"))
    page.locator("[data-replace-commit]").click()
    page.wait_for_selector("[data-replace-strip]", state="detached")
    page.wait_for_selector('.asset-cell .asset-dname:has-text("second.png")')


@pytest.mark.django_db(transaction=True)
def test_a_filter_swap_mid_flight_still_updates_the_cell(page, live_server):
    """The replace POST must still be in flight while the filter swaps the grid,
    so the 200 lands on a detached strip and takes the re-query branch.

    CAPTURE-AND-RELEASE, the pattern this suite already uses
    (tests/test_e2e_builder_toggle.py:352, tests/test_e2e_inline_rename.py:326).
    A route handler that returns without fulfil/continue_/abort leaves the
    request PENDING -- test_two_overlapping_tree_fetches_stay_busy_until_both
    _settle asserts TWO are simultaneously in flight before releasing them one
    at a time, which could not happen if returning auto-continued.

    Do NOT block inside the handler waiting on an Event. The comment at
    test_e2e_builder_toggle.py:347-349 says why: "Sleeping inside a sync route
    handler serialises the driver" -- the click would not return, the filter
    would run only after the POST was released, and the branch under test would
    never be exercised while the test still passed.
    """
    _, course, _unit, asset = _seed("pa-repl-filter", "repl-filter")
    _open_manager(page, live_server, "pa-repl-filter", course)

    held = []
    page.route("**/replace/", lambda route: held.append(route))

    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(_upload_payload("late.png"))
    page.locator("[data-replace-commit]").click()

    # Prove the POST actually dispatched before touching the filter: the commit
    # handler disables the button synchronously, immediately before fetch().
    page.wait_for_function(
        "() => { const b = document.querySelector('[data-replace-commit]');"
        "        return b && b.disabled; }"
    )
    for _ in range(50):  # bounded poll on a real condition, not a blind sleep
        if held:
            break
        page.wait_for_timeout(100)
    assert len(held) == 1, "the replace POST never reached the route"

    # Force oldGrid.replaceWith(newGrid) while the POST is still held.
    page.fill("[data-filter-q]", "original")
    page.wait_for_selector("[data-replace-strip]", state="detached")

    held[0].continue_()

    page.wait_for_selector('.asset-cell .asset-dname:has-text("late.png")')
    asset.refresh_from_db()
    assert asset.original_filename == "late.png"
    # The re-query branch moves NO focus: the element that had it is long gone
    # with the swapped-away grid, and stealing focus back would yank a keyboard
    # user out of the filter box they are still typing in.
    assert page.evaluate(
        "() => document.activeElement === document.querySelector('[data-filter-q]')"
    )


@pytest.mark.django_db(transaction=True)
def test_a_filter_that_hides_the_asset_mid_flight_is_a_no_op(page, live_server):
    """The negative half of the re-query branch: `if (live)` is false.

    Filtering the asset OUT means root.querySelector(...) finds nothing, so the
    200 must quietly do nothing rather than throw. Without this the `if (live)`
    guard could be deleted and every other test would stay green.
    """
    _, course, _unit, asset = _seed("pa-repl-gone", "repl-gone")
    _open_manager(page, live_server, "pa-repl-gone", course)

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    held = []
    page.route("**/replace/", lambda route: held.append(route))
    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(_upload_payload("hidden.png"))
    page.locator("[data-replace-commit]").click()
    page.wait_for_function(
        "() => { const b = document.querySelector('[data-replace-commit]');"
        "        return b && b.disabled; }"
    )
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(100)
    assert len(held) == 1

    page.fill("[data-filter-q]", "zzz-matches-nothing")
    page.wait_for_selector(".asset-cell", state="detached")

    # Synchronise on the response, not the clock: the assertions below are only
    # meaningful once the 200 has actually been handled.
    with page.expect_response("**/replace/"):
        held[0].continue_()
    page.wait_for_timeout(100)  # a short settle for the handler, after the wait

    assert errors == [], errors
    assert page.locator(".asset-cell").count() == 0
    asset.refresh_from_db()
    assert asset.original_filename == "hidden.png"  # the replace still committed


@pytest.mark.django_db(transaction=True)
def test_a_grid_swap_while_the_file_chooser_is_open_still_lands(page, live_server):
    """The exact window the hoisted-input fix exists for: the OS file dialog is
    still open -- pendingReplacePk already recorded by the ⇄ click -- when the
    debounced filter does oldGrid.replaceWith(newGrid).

    A per-cell input would be detached at that swap: its `change` would bubble
    only inside the orphaned tree and never reach the delegated listener on
    .media-manager, so choosing a file afterwards would be a dead click -- no
    strip, no flash, no error. The shared input lives outside .asset-grid, so
    the swap cannot touch it, and the change handler re-resolves the (freshly
    re-rendered) cell from the live DOM by the recorded pk.
    """
    _, course, _unit, asset = _seed("pa-repl-chooser-swap", "repl-chooser-swap")
    _open_manager(page, live_server, "pa-repl-chooser-swap", course)

    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    # Stamp the grid, then wait for the stamp to disappear -- a real
    # post-swap condition rather than a blind sleep. A sleep short enough to
    # be fast is also short enough to occasionally run BEFORE the debounce
    # plus round trip lands, which would silently degrade this into a
    # duplicate of the happy-path test rather than exercising the window it
    # is named for.
    page.evaluate(
        "document.querySelector('.asset-grid').setAttribute('data-pre-swap','')"
    )
    page.fill("[data-filter-q]", "original")  # still matches original.png
    page.wait_for_selector(".asset-grid:not([data-pre-swap])")  # the swap landed
    fc.value.set_files(_upload_payload("after-swap.png"))

    strip = page.locator("[data-replace-strip]")
    strip.wait_for(state="visible")
    strip.locator("[data-replace-commit]").click()

    page.wait_for_selector("[data-replace-strip]", state="detached")
    page.wait_for_selector('.asset-cell .asset-dname:has-text("after-swap.png")')
    asset.refresh_from_db()
    assert asset.original_filename == "after-swap.png"


@pytest.mark.django_db(transaction=True)
def test_an_upload_after_filtering_lands_in_the_live_grid(page, live_server):
    """wireManager used to capture `grid = root.querySelector(".asset-grid")`
    once, at wire time. The debounced filter's oldGrid.replaceWith(newGrid)
    (exercised above by the replace-vs-filter tests) detaches that captured
    node, so insertCell's grid.prepend(cell) landed in an orphan -- an upload
    performed after filtering never appeared. insertCell must re-query the
    live grid from root on every call instead.
    """
    _, course, _unit, _asset = _seed("pa-upload-after-filter", "upload-after-filter")
    _open_manager(page, live_server, "pa-upload-after-filter", course)

    # Force oldGrid.replaceWith(newGrid) -- the same stamp-and-wait pattern as
    # test_a_grid_swap_while_the_file_chooser_is_open_still_lands: a real
    # post-swap condition, not a blind sleep.
    page.evaluate(
        "document.querySelector('.asset-grid').setAttribute('data-pre-swap','')"
    )
    page.fill("[data-filter-q]", "original")  # still matches original.png
    page.wait_for_selector(".asset-grid:not([data-pre-swap])")  # the swap landed

    page.set_input_files(
        ".media-upload input[type='file']", _upload_payload("after-filter.png")
    )
    page.click(".media-upload button[type='submit']")

    # Scoped to .asset-grid, the LIVE node: if insertCell had prepended into
    # the grid captured at wire time (now detached), this selector would
    # never resolve and the test would time out rather than fail cleanly.
    page.wait_for_selector(
        '.asset-grid .asset-cell .asset-dname:has-text("after-filter.png")'
    )


@pytest.mark.django_db(transaction=True)
def test_a_grid_swap_to_no_match_while_the_chooser_is_open_is_noop(page, live_server):
    """The negative half of the same window: the filter's query matches
    nothing, so the swapped-in grid has no cell at all and the change
    handler's re-resolve-by-pk finds nothing. Nothing must throw and no strip
    may appear -- without this the `if (!cell)` guard in the change handler
    could be deleted and the positive test above would still pass.
    """
    _, course, _unit, asset = _seed("pa-repl-chooser-nomatch", "repl-chooser-nomatch")
    _open_manager(page, live_server, "pa-repl-chooser-nomatch", course)

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    page.fill("[data-filter-q]", "zzz-matches-nothing")
    page.wait_for_selector(".empty-state")  # the swap has landed; no cell left
    fc.value.set_files(_upload_payload("after-swap.png"))
    page.wait_for_timeout(200)  # a no-op has no event to sync on; short settle

    assert errors == [], errors
    assert page.locator("[data-replace-strip]").count() == 0
    # The `!cell` branch's input.value = "" is otherwise untested: without
    # this assertion that clear could be deleted and every other test in
    # this module would still be green.
    assert page.input_value("[data-replace-input]") == ""
    asset.refresh_from_db()
    assert asset.original_filename == "original.png"  # unchanged


@pytest.mark.django_db(transaction=True)
def test_a_strip_discarded_by_a_grid_swap_does_not_deaden_the_next_pick(
    page, live_server, tmp_path
):
    """Finding-1 regression: a strip destroyed WITHOUT going through
    closeStrip -- here, the filter's oldGrid.replaceWith(newGrid) -- used to
    leave the shared input's value behind. `change` fires only on a value
    CHANGE, so re-picking the exact same file on the next ⇄ was a silent dead
    click: no strip, no flash, nothing. The ⇄ click handler now clears
    replaceInput.value before every dialog open, regardless of how the
    previous strip died, so this sequence must still land a strip.

    Uses the SAME real path on disk for both picks, via set_files(str(path))
    rather than the buffer-dict form _upload_payload() builds. A buffer
    upload gets a fresh synthetic backing file (and therefore a distinct
    browser-internal path) on every call, which papers over the exact bug
    this test exists to catch: a real OS file dialog reports the identical
    fakepath string for the identical file on disk, and it is THAT equality
    the browser uses to decide whether to fire `change` at all.
    """
    _, course, _unit, _asset = _seed("pa-repl-dead-strip", "repl-dead-strip")
    _open_manager(page, live_server, "pa-repl-dead-strip", course)

    same_file = tmp_path / "new-diagram.png"
    same_file.write_bytes(_png_bytes(color="purple"))

    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(str(same_file))
    strip = page.locator("[data-replace-strip]")
    strip.wait_for(state="visible")

    # Discard the strip via a grid swap, NOT cancel/commit -- oldGrid
    # .replaceWith(newGrid) removes the whole subtree the strip lives in,
    # bypassing closeStrip entirely. "original" still matches original.png,
    # so the asset (and its ⇄) remain in the swapped-in grid.
    page.fill("[data-filter-q]", "original")
    page.wait_for_selector("[data-replace-strip]", state="detached")

    # Re-open on the same asset and pick the SAME path again. Without the
    # fix the shared input's value is still that path, set_files with the
    # identical path fires no `change`, and no strip ever appears.
    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(str(same_file))
    strip = page.locator("[data-replace-strip]")
    strip.wait_for(state="visible")
    assert "new-diagram.png" in strip.locator("[data-replace-filename]").inner_text()


@pytest.mark.django_db(transaction=True)
def test_the_accept_attribute_matches_the_clicked_assets_kind(page, live_server):
    """`accept` moved off the server-rendered per-cell markup onto the shared
    input, set by the ⇄ click handler at open time. Every other e2e asset in
    this module is an image, so a build that hardcoded accept="image/*" would
    pass all of them while silently hiding every video file from the OS
    dialog when replacing a video asset.
    """
    from django.core.files.uploadedfile import SimpleUploadedFile

    from courses.models import MediaAsset

    _, course, _unit, _asset = _seed("pa-repl-accept", "repl-accept")
    video = MediaAsset.objects.create(
        course=course,
        kind="video",
        file=SimpleUploadedFile("v.mp4", b"\x00" * 256),
        original_filename="v.mp4",
    )
    _open_manager(page, live_server, "pa-repl-accept", course)

    cell = page.locator(f'.asset-cell[data-asset-id="{video.pk}"]')
    with page.expect_file_chooser() as fc:
        cell.locator("[data-replace-asset]").click()
    accept = page.get_attribute("[data-replace-input]", "accept")
    fc.value.set_files(
        {"name": "v2.mp4", "mimeType": "video/mp4", "buffer": b"\x00" * 256}
    )
    assert accept == "video/*"


@pytest.mark.django_db(transaction=True)
def test_the_drag_warning_appears_only_for_a_drag_to_image_asset(page, live_server):
    from courses.models import DragToImageQuestionElement

    _, course, unit, plain = _seed("pa-repl-warn", "repl-warn", with_element=False)
    dragged = make_image_asset(course, filename="diagram.png", color="green")
    add_element(
        unit,
        DragToImageQuestionElement.objects.create(
            media=dragged, alt="Diagram", distractors=""
        ),
    )
    _open_manager(page, live_server, "pa-repl-warn", course)

    for pk, expect_warning in ((dragged.pk, True), (plain.pk, False)):
        cell = page.locator(f'.asset-cell[data-asset-id="{pk}"]')
        # Click THIS cell's ⇄: with the input shared across the manager, the
        # click is what records which asset (and its data-kind) the dialog is
        # for -- cell.locator("[data-replace-input]") would find nothing, since
        # the input no longer lives inside any cell.
        with page.expect_file_chooser() as fc:
            cell.locator("[data-replace-asset]").click()
        fc.value.set_files(_upload_payload())
        strip = cell.locator("[data-replace-strip]")
        strip.wait_for(state="visible")
        shown = cell.locator(".asset-replace-confirm__warn").count() > 0
        assert shown is expect_warning, pk
        # Without these, msg(root, "replace-aria", ...) could be deleted
        # entirely and every test in this module would still pass.
        assert strip.get_attribute("role") == "group"
        assert strip.get_attribute("aria-label")
        cell.locator("[data-replace-cancel]").click()
        page.wait_for_selector("[data-replace-strip]", state="detached")


@pytest.mark.django_db(transaction=True)
def test_screenshots_light_and_dark(page, live_server, tmp_path):
    """Four foot states at the grid's 360px-viewport column width, both themes.

    Set User.theme, NOT the libli_theme cookie: an authed user's theme wins
    outright in _resolve_theme_pref, so the cookie route silently renders light.

    360px viewport: .asset-grid is repeat(auto-fill, minmax(8rem, 1fr)), which
    at this width renders two auto-fill columns WIDENED by 1fr to ~158px each
    (measured in tests/test_zz_scratch_measure.py), not the 128px 8rem floor --
    the floor is a minimum, not the rendered width. A narrow window is still
    what makes the shrink and truncation rules bite; at desktop width they
    never engage.
    """
    owner, course, unit, in_use = _seed("pa-repl-shots", "repl-shots")
    unused = make_image_asset(course, filename="nobody-uses-me.png", color="green")
    page.set_viewport_size({"width": 360, "height": 900})
    _login(page, live_server, "pa-repl-shots")
    url = f"{live_server.url}/manage/courses/{course.slug}/media/"

    for theme in ("light", "dark"):
        owner.theme = theme
        owner.save(update_fields=["theme"])
        page.goto(url)
        page.wait_for_selector(".asset-cell")
        assert page.locator("html").get_attribute("data-theme") == theme

        unused_cell = page.locator(f'.asset-cell[data-asset-id="{unused.pk}"]')
        in_use_cell = page.locator(f'.asset-cell[data-asset-id="{in_use.pk}"]')

        # 1. unused -- the majority case, and what the .muted truncation is for
        unused_cell.screenshot(path=str(tmp_path / f"replace-{theme}-1-unused.png"))

        # 2. in use, <details> CLOSED -- the only state :not([open]) targets.
        #    Expect the summary truncated and the "▸" marker eaten by the
        #    ellipsis: accepted, but look at it.
        in_use_cell.screenshot(path=str(tmp_path / f"replace-{theme}-2-closed.png"))

        # 3. in use, <details> OPEN -- deliberately left at min-content
        in_use_cell.locator("summary.asset-uses").click()
        page.wait_for_selector("details.asset-uses-detail[open]")
        in_use_cell.screenshot(path=str(tmp_path / f"replace-{theme}-3-open.png"))
        in_use_cell.locator("summary.asset-uses").click()

        # 4. confirm strip open, captured across the WHOLE grid so the
        #    row-height reflow onto the sibling cell is visible
        with page.expect_file_chooser() as fc:
            in_use_cell.locator("[data-replace-asset]").click()
        fc.value.set_files(_upload_payload("a-rather-long-replacement-name.png"))
        page.wait_for_selector("[data-replace-strip]")
        page.locator(".asset-grid").screenshot(
            path=str(tmp_path / f"replace-{theme}-4-strip-row.png")
        )
        page.locator("[data-replace-cancel]").click()
        page.wait_for_selector("[data-replace-strip]", state="detached")

    print(f"REPLACE_SHOTS_DIR={tmp_path}")


@pytest.mark.django_db(transaction=True)
def test_rename_prefills_the_untruncated_name(page, live_server):
    """The span now renders head...tail. Seeding the input from its textContent
    and letting blur commit would write the ellipsis into the DB permanently.
    """
    long_name = "przykladowa_bardzo_dluga_nazwa_wersja_0_2.png"
    user, course = _seed_assets("rename-pa", "rename-seed", (long_name, (400, 300)))
    _open_manager(page, live_server, "rename-pa", course)
    page.locator("[data-rename-asset]").first.click()
    # expect() here is not decoration: ruff's F401 is live (pyproject.toml:36
    # selects "F", and tests/** ignores only S105/S106/S107), so the import
    # added in Step 1 must be USED in this task or `ruff check` fails at this
    # task's commit.
    expect(page.locator(".asset-rename-input")).to_be_visible()
    value = page.locator(".asset-rename-input").input_value()
    # Cancel BEFORE anything moves focus: blur commits with save=true, so on a
    # broken build simply finishing the test would write the truncated name.
    page.keyboard.press("Escape")
    assert value == long_name
    assert "…" not in value


# Card width at the 360px viewport, measured via tests/test_zz_scratch_measure.py
# (a throwaway spike, not committed): 158px. Two auto-fill 1fr columns, not the
# minmax(8rem, 1fr) 128px floor -- see test_screenshots_light_and_dark's
# corrected docstring below.


@pytest.mark.django_db(transaction=True)
def test_a_long_name_stays_inside_its_card(page, live_server):
    """The reported bug: .asset-dname had NO truncation rule, so as a flex item
    with min-width:auto it refused to shrink below the whole string's
    min-content width and spilled under the next card, which painted over it.
    """
    user, course = _seed_assets(
        "geo1-pa", "geo1", ("przykladowa_parabola_0_2.png", (400, 300))
    )
    _open_manager(page, live_server, "geo1-pa", course)
    page.set_viewport_size({"width": 360, "height": 900})
    rects = page.evaluate("""() => {
        const s = document.querySelector('.asset-dname');
        const r = document.createRange(); r.selectNodeContents(s);
        return Array.from(r.getClientRects()).map(
            x => ({right: x.right, bottom: x.bottom})
        );
    }""")
    card = page.locator(".asset-cell").first.bounding_box()
    assert rects, "no text runs measured"
    for rect in rects:
        assert rect["right"] <= card["x"] + card["width"] + 1


@pytest.mark.django_db(transaction=True)
def test_two_similar_names_each_paint_their_own_suffix_inside_the_card(
    page, live_server
):
    """`:has-text()` is NOT an acceptable probe here -- it matches the element's
    text CONTENT, which is unchanged when the text is merely clipped, so the
    mutant would stay green. Measure the rect covering the suffix instead.

    _seed_assets, NOT the file's _seed(): this row iterates EVERY .asset-cell
    and compares the suffix set, so _seed's own `original.png` would add a third
    cell (suffix "inal.png") and the row would be red on a correct build.
    """
    user, course = _seed_assets(
        "geo2-pa",
        "geo2",
        ("przykladowa_parabola_0_1.png", (400, 300)),
        ("przykladowa_parabola_0_2.png", (400, 300)),
    )
    _open_manager(page, live_server, "geo2-pa", course)
    page.set_viewport_size({"width": 360, "height": 900})
    painted = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('.asset-cell')).map(cell => {
            const s = cell.querySelector('.asset-dname');
            const text = s.textContent;
            const start = text.length - 8;            // "_0_1.png"
            const r = document.createRange();
            r.setStart(s.firstChild, start);
            r.setEnd(s.firstChild, text.length);
            const rect = r.getBoundingClientRect();
            const card = cell.getBoundingClientRect();
            return {
                suffix: text.slice(start),
                inside: rect.width > 0 && rect.right <= card.right + 1
                        && rect.bottom <= card.bottom + 1,
            };
        });
    }""")
    assert {p["suffix"] for p in painted} == {"_0_1.png", "_0_2.png"}
    assert all(p["inside"] for p in painted)


@pytest.mark.django_db(transaction=True)
def test_the_pencil_button_stays_on_the_first_line(page, live_server):
    """Flex line breaking uses each item's HYPOTHETICAL main size, so with the
    default flex-basis:auto the span's max-content width pushes the button onto
    flex line 2. align-items cannot fix that -- it aligns WITHIN a line.

    The fixture must wrap to at least two lines at the MEASURED card width
    (Step 1): on a single-line name both mutants leave the button vertically
    coincident with the span and this row passes on a broken build.
    """
    user, course = _seed_assets(
        "geo3-pa", "geo3", ("przykladowa_parabola_0_2.png", (400, 300))
    )
    _open_manager(page, live_server, "geo3-pa", course)
    page.set_viewport_size({"width": 360, "height": 900})
    lines = page.evaluate("""() => {
        const s = document.querySelector('.asset-dname');
        const r = document.createRange(); r.selectNodeContents(s);
        return r.getClientRects().length;
    }""")
    assert lines >= 2, "fixture does not wrap; the mutants cannot discriminate"
    span = page.locator(".asset-dname").first.bounding_box()
    # The pencil is opacity:0 until its cell is hovered (editor.css:725-726),
    # so probe bounding_box() -- do NOT assert visibility.
    pen = page.locator("[data-rename-asset]").first.bounding_box()
    assert abs(pen["y"] - span["y"]) <= 1


@pytest.mark.django_db(transaction=True)
def test_a_32_char_name_clamps_to_three_lines(page, live_server):
    """Resolves Step 7's clamp question: a <=32-char name CAN overflow three
    lines at the measured 158px card width -- spiked in
    tests/test_zz_scratch_measure.py (deleted, not committed) with this exact
    32-char fixture. Without the clamp it wraps to 4 lines (scrollHeight ==
    clientHeight == 86px); with it, the box holds at 3 (scrollHeight 86px >
    clientHeight 65px). So the clamp is reachable in production, not just in
    a synthetic test, and the four declarations stay.

    `getClientRects()` does NOT discriminate here: the same spike measured 5
    rects WITH the clamp and 4 WITHOUT it -- Blink lays out every wrapped line
    and returns a rect for each regardless of `-webkit-line-clamp`, so
    "exactly 3 rects" would be unfalsifiable. `scrollHeight > clientHeight`
    is what actually separates a clamped box (client height pinned to 3
    lines, scroll height taller) from an unclamped one (both grow together
    and stay equal) -- mutant: drop `-webkit-line-clamp: 3`.

    The fixture is exactly 32 characters -- middle_truncate's own budget -- so
    the length assertion below is what would fail loudly if that budget ever
    shrank under this test: below 32, middle_truncate would elide the middle
    and the fixture would stop exercising the clamp for a different reason.
    """
    name = "mmmmmmmmmmmmmmmmmmmmmmmmmmmm.png"
    assert len(name) == 32
    user, course = _seed_assets("geo4-pa", "geo4", (name, (400, 300)))
    _open_manager(page, live_server, "geo4-pa", course)
    page.set_viewport_size({"width": 360, "height": 900})
    rendered = page.evaluate("document.querySelector('.asset-dname').textContent")
    assert rendered == name  # untouched by middle_truncate's budget
    metrics = page.evaluate("""() => {
        const s = document.querySelector('.asset-dname');
        return {scrollHeight: s.scrollHeight, clientHeight: s.clientHeight};
    }""")
    assert metrics["scrollHeight"] > metrics["clientHeight"]


@pytest.mark.django_db(transaction=True)
def test_hover_opens_the_overlay_with_the_thumbnails_source(page, live_server):
    # size= is mandatory: make_image_asset defaults to (1,1) (factories.py:150),
    # which makes "larger than the thumb" unachievable or true for the wrong
    # reason.
    user, course = _seed_assets("hov-pa", "hov", ("wide_0_1.png", (800, 200)))
    _open_manager(page, live_server, "hov-pa", course)
    _open_preview(page, "wide_0_1.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
    # currentSrc on BOTH sides. Comparing raw attributes does not work here:
    # open() assigns anchor.currentSrc, which is the ABSOLUTE resolved URL, so
    # the overlay's attribute is "http://127.0.0.1:PORT/media/..." while the
    # thumb's is the relative "/media/..." the template wrote (MEDIA_URL is
    # "/media/", config/settings/base.py:167, not overridden in test.py). They
    # are never equal. The visibility wait above guarantees both are populated,
    # which is what made the attribute form tempting in the first place.
    same = page.evaluate("""() => {
        const img = document.querySelector('[data-asset-preview-img]');
        const thumb = document.querySelector('[data-asset-preview]');
        return img.currentSrc === thumb.currentSrc;
    }""")
    assert same
    box = page.locator(".asset-preview").bounding_box()
    thumb = _anchor(page, "wide_0_1.png").bounding_box()
    assert box["width"] > thumb["width"]


@pytest.mark.django_db(transaction=True)
def test_a_non_4_3_source_shows_its_full_extent(page, live_server):
    """The crop comes from .asset-thumb's OWN aspect-ratio + object-fit:cover.
    The overlay image is a separate element that simply does not carry them.

    Fixture and viewport are chosen so the image does NOT hit the container's
    max-height: at 1280x900 the budget is ~884px and a 200x400 source in a
    ~302px content box wants ~604px. A taller source would be SHRUNK by
    flex:0 1 auto (which the tall-portrait row asserts), so its element box
    would no longer carry the source's ratio.
    """
    user, course = _seed_assets("n43-pa", "n43", ("portret_0_1.png", (200, 400)))
    _open_manager(page, live_server, "n43-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open_preview(page, "portret_0_1.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
    ratio = page.evaluate("""() => {
        const el = document.querySelector('[data-asset-preview-img]');
        const r = el.getBoundingClientRect();
        return r.width / r.height;
    }""")
    assert abs(ratio - 200 / 400) < 0.05


@pytest.mark.django_db(transaction=True)
def test_a_small_source_still_previews_larger_than_the_thumb(page, live_server):
    # Short name + small size, both deliberate: with a normal-length name the
    # mutant's shrink-wrapped box would be sized by the caption (~160px, already
    # wider than a ~115px thumb) and the row would stay green.
    user, course = _seed_assets("sml-pa", "sml", ("s.png", (40, 30)))
    _open_manager(page, live_server, "sml-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open_preview(page, "s.png")
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
    img = page.locator("[data-asset-preview-img]").bounding_box()
    thumb = page.locator("[data-asset-preview]").first.bounding_box()
    assert img["width"] > thumb["width"]


@pytest.mark.django_db(transaction=True)
def test_an_over_budget_name_is_readable_in_the_caption(page, live_server):
    # ~58 characters of unbroken [a-z0-9_]. The caption's content box is ~302px
    # (320 less padding and border) and .72rem Inter is ~6px/char, so a 38-char
    # name -- "over budget" for middle_truncate at 32 -- still fits on ONE line
    # and the mutant would survive. No hyphens: they are soft-wrap opportunities
    # and would let the text wrap without overflow-wrap: anywhere.
    long_caption = "przykladowa_bardzo_dluga_nazwa_pliku_z_wykresem_funkcji_0_2.png"
    user, course = _seed_assets("cap-pa", "cap", (long_caption, (400, 300)))
    _open_manager(page, live_server, "cap-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open_preview(page, long_caption)
    clipped = page.evaluate("""() => {
        const cap = document.querySelector('.asset-preview__caption');
        return cap.scrollWidth > cap.clientWidth;
    }""")
    assert not clipped


@pytest.mark.django_db(transaction=True)
def test_the_caption_is_written_as_text_not_markup(page, live_server):
    """getAttribute returns data-name FULLY DECODED, so the server-side escaping
    that protects the card gives the overlay no protection at all. Nothing else
    in the suite would go red if textContent became innerHTML."""
    hostile = "<img src=x onerror=1>.png"
    user, course = _seed_assets("xss-pa", "xss-e2e", (hostile, (400, 300)))
    _open_manager(page, live_server, "xss-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open_preview(page, hostile)
    assert page.locator(".asset-preview__caption").text_content() == hostile
    injected = page.evaluate(
        """() => document.querySelectorAll('.asset-preview img').length"""
    )
    assert injected == 1  # only [data-asset-preview-img]


@pytest.mark.django_db(transaction=True)
def test_a_tall_source_is_clamped_and_lands_centred_at_360(page, live_server):
    """Centred is the LAST branch of place()'s five-way ladder and the only one
    any test reaches -- assert it was taken, or the clamp alone would satisfy
    an inside-the-viewport check from any branch."""
    user, course = _seed_assets("tll-pa", "tll", ("wysoki_0_1.png", (400, 2000)))
    _open_manager(page, live_server, "tll-pa", course)
    page.set_viewport_size({"width": 360, "height": 900})
    _open_preview(page, "wysoki_0_1.png")
    # Without this wait the image is display:none, its rect is all zeros, and
    # `inside(i)` is trivially true -- which would let the min-height mutant pass.
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
    result = page.evaluate("""() => {
        const vw = document.documentElement.clientWidth;
        const vh = document.documentElement.clientHeight;
        const o = document.querySelector('.asset-preview').getBoundingClientRect();
        const imgEl = document.querySelector('[data-asset-preview-img]');
        const i = imgEl.getBoundingClientRect();
        const inside = b =>
            b.left >= 0 && b.top >= 0 && b.right <= vw && b.bottom <= vh;
        return {
            fits: inside(o) && inside(i),
            imgHeight: i.height,
            dx: Math.abs((o.left + o.width / 2) - vw / 2),
            dy: Math.abs((o.top + o.height / 2) - vh / 2),
        };
    }""")
    assert result["imgHeight"] > 0, "a zero rect would satisfy `fits` vacuously"
    assert result["fits"]
    assert result["dx"] <= 2 and result["dy"] <= 2


@pytest.mark.django_db(transaction=True)
def test_hovering_the_covered_neighbour_switches_the_overlay(page, live_server):
    """pointer-events:none is load-bearing: the overlay necessarily covers the
    neighbouring cell, and without it Playwright reports the overlay
    intercepting and the neighbour can never be hovered.

    Seed a FULL ROW, not two assets. `.app-main` caps at 960px
    (core/static/core/css/app.css:34), so at 1280x900 the grid is ~920px wide
    and minmax(8rem, 1fr) yields SIX columns of ~143px. With two cells the
    320px overlay lands in empty grid area, the probe below returns null, and
    this row's own guard assertion fails on a correct build.
    """
    specs = [(f"sasiad_{i}_0.png", (400, 300)) for i in range(8)]
    user, course = _seed_assets("cov-pa", "cov", *specs)
    _open_manager(page, live_server, "cov-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _open_preview(page, "sasiad_0_0.png")
    # Identify the covered neighbour from the MEASURED overlay box rather than
    # assuming which cell it lands on -- and return its NAME, not an ordinal:
    # a cell index and a [data-asset-preview] index only align while every
    # asset is an image.
    covered = page.evaluate("""() => {
        const o = document.querySelector('.asset-preview').getBoundingClientRect();
        const hit = Array.from(document.querySelectorAll('.asset-cell')).find(c => {
            const r = c.getBoundingClientRect();
            return r.left < o.right && r.right > o.left
                && r.top < o.bottom && r.bottom > o.top
                && c.getAttribute('data-name') !== 'sasiad_0_0.png';
        });
        return hit ? hit.getAttribute('data-name') : null;
    }""")
    assert covered, "the overlay covers no neighbour; widen the fixture row"
    _open_preview(page, covered)
    expect(page.locator(".asset-preview__caption")).to_have_text(covered)


@pytest.mark.django_db(transaction=True)
def test_a_cell_from_a_swapped_in_grid_still_opens_the_overlay(page, live_server):
    """The whole justification for delegating mouseover/mouseout: the debounced
    filter replaces the entire .asset-grid, and per-node listeners bound at load
    would go silently dead on every swapped-in cell.

    The anchor must provably be a NEW node. Filtering straight to a name that is
    already in the initial grid only narrows it -- the wait matches the
    PRE-swap node instantly, the wait is a no-op, and the row would open on the
    old cell (green for the wrong reason, since the load-time listener the
    mutant installs is on exactly that node). Filter it OUT first, wait for the
    detach, then filter it back in.
    """
    user, course = _seed_assets("swg-pa", "swg", ("filtrowany_0_1.png", (400, 300)))
    _open_manager(page, live_server, "swg-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.fill("[data-filter-q]", "brak-dopasowania")
    page.wait_for_selector(".asset-grid .asset-cell", state="detached")
    page.fill("[data-filter-q]", "filtrowany")
    page.wait_for_selector('.asset-grid .asset-cell[data-name="filtrowany_0_1.png"]')
    _open_preview(page, "filtrowany_0_1.png")
    expect(page.locator(".asset-preview__caption")).to_have_text("filtrowany_0_1.png")


@pytest.mark.django_db(transaction=True)
def test_an_anchor_detached_during_the_dwell_opens_nothing(page, live_server):
    """A detached anchor measures as zeros, so "fits on the right" trivially
    passes and the overlay pins to the corner with no anchor left to close it.

    Do NOT drive this with the filter: media_picker.js:651 debounces at
    setTimeout(runFilter, 250) -- exactly DWELL_MS -- and then waits on a fetch,
    so the swap always lands AFTER the dwell has already opened. Detach the node
    directly instead, which is deterministic and needs no timing argument.
    """
    user, course = _seed_assets("dwl-pa", "dwl", ("znikajacy_0_1.png", (400, 300)))
    _open_manager(page, live_server, "dwl-pa", course)
    page.set_viewport_size({"width": 1280, "height": 900})
    _anchor(page, "znikajacy_0_1.png").hover()  # start the dwell
    page.evaluate("() => document.querySelector('.asset-cell').remove()")
    page.wait_for_timeout(600)  # outlive the dwell
    expect(page.locator(".asset-preview")).to_be_hidden()
